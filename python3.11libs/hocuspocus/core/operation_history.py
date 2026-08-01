"""SQLite-backed authenticated terminal tool-result reconciliation."""

from __future__ import annotations

import copy
from hashlib import sha256
import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

from .operation_journal import JournalIdentity, JournalPlatform
from .paths import operation_history_path


MAX_RECORDS = 256
MAX_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024 * 1024
RETENTION_SECONDS = 24 * 60 * 60
HOST_LEASE_SECONDS = 10.0
HOST_HEARTBEAT_SECONDS = 2.0
SESSION_POLICY_PRINCIPAL = "principal_bound"
JOURNAL_SLOT_BYTES = MAX_RECORD_BYTES + 16 * 1024
JOURNAL_MAX_BYTES = MAX_BYTES
JOURNAL_MAX_FILES = 256
JOURNAL_SCAN_LIMIT = 512
JOURNAL_ORPHAN_GRACE_SECONDS = 30.0
_OPERATION_ID = re.compile(r"op:[0-9a-f]{32}")
_PHYSICAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\]|/(?:Users|home|tmp|var|etc|mnt|opt|private|Volumes)/)"
)
_HOUDINI_PATH = re.compile(
    r"^/(?:obj|stage|mat|out|tasks|ch|img|shop)(?:/|$)"
)
_SENSITIVE_KEYS = {
    "authorization", "content", "dirtybuffer", "dirtysource", "details",
    "filesystempath", "hdafilepath", "libraryfilepath", "physicalpath",
    "secret", "source", "sourcetext", "token",
}


@dataclass(frozen=True)
class _PreparedTerminal:
    state: str
    commit_state: str
    finished_at: float
    result_json: str | None
    error_json: str | None
    byte_length: int


def argument_digest(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(
        arguments,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def valid_operation_id(value: Any) -> bool:
    return isinstance(value, str) and _OPERATION_ID.fullmatch(value) is not None


def new_operation_id() -> str:
    return f"op:{uuid4().hex}"


def commit_state_for_result(
    result: dict[str, Any], annotations: dict[str, Any]
) -> str:
    if annotations.get("readOnlyHint") is True:
        return "not_applicable"
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and (
        structured.get("applied") is False
        or structured.get("cancelled") is True
    ):
        return "not_committed"
    return "committed"


def attach_operation_metadata(
    result: dict[str, Any],
    *,
    operation_id: str,
    tool_name: str,
    host_instance_id: str,
    host_generation: int,
    commit_state: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(result)
    metadata = payload.setdefault("_meta", {})
    if not isinstance(metadata, dict):
        metadata = {}
        payload["_meta"] = metadata
    metadata["hocuspocus/operation"] = {
        "operationId": operation_id,
        "toolName": tool_name,
        "hostInstanceId": host_instance_id,
        "hostGeneration": host_generation,
        "deliveryStage": "terminal",
        "commitState": commit_state,
    }
    return payload


def error_from_terminal(payload: dict[str, Any]) -> NoReturn:
    from hocuspocus.core.jsonrpc import JsonRpcError

    data = payload.get("data")
    raise JsonRpcError(
        int(payload.get("code", -32603)),
        str(payload.get("message", "Terminal operation failed.")),
        copy.deepcopy(data) if isinstance(data, dict) else None,
        retryable=(data.get("retryable") if isinstance(data, dict) else None),
    )


class OperationHistory:
    def __init__(
        self,
        path: Path | None = None,
        *,
        host_instance_id: str | None = None,
        host_generation: int | None = None,
        journal_directory_flusher: Any | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._path = path or operation_history_path()
        self._journal_dir = self._path.parent / f"{self._path.name}.journal"
        self._journal_platform = JournalPlatform(
            self._journal_dir,
            JOURNAL_SLOT_BYTES,
            directory_flusher=journal_directory_flusher,
        )
        self._connection = sqlite3.connect(
            self._path, timeout=5.0, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._lease_identity = (
            (host_instance_id, host_generation)
            if host_instance_id is not None and host_generation is not None
            else None
        )
        self._lease_token = uuid4().hex
        self._lease_stop = threading.Event()
        self._lease_thread: threading.Thread | None = None
        self._journal_over_capacity = False
        self._initialize()
        if self._lease_identity is not None:
            self._start_lease()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS operation_history (
                    principal_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    session_id TEXT,
                    host_instance_id TEXT NOT NULL,
                    host_generation INTEGER NOT NULL,
                    argument_digest TEXT NOT NULL,
                    session_policy TEXT NOT NULL,
                    state TEXT NOT NULL,
                    admitted_at REAL NOT NULL,
                    finished_at REAL,
                    delivery_stage TEXT NOT NULL,
                    commit_state TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    recovery_json TEXT NOT NULL,
                    journal_name TEXT,
                    journal_device INTEGER,
                    journal_inode INTEGER,
                    byte_length INTEGER NOT NULL,
                    PRIMARY KEY (principal_id, operation_id)
                )
            """)
            self._migrate_locked()
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS operation_host_leases (
                    host_instance_id TEXT NOT NULL,
                    host_generation INTEGER NOT NULL,
                    lease_token TEXT NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    PRIMARY KEY (host_instance_id, host_generation)
                )
            """)
            self._recover_journals_locked()
            self._prune_locked(time.time())

    def close(self) -> None:
        self._lease_stop.set()
        if self._lease_thread is not None:
            self._lease_thread.join(timeout=HOST_HEARTBEAT_SECONDS * 2)
        with self._lock:
            self._release_lease_locked()
            self._connection.close()

    def advance_host(self, host_instance_id: str, host_generation: int) -> None:
        with self._lock, self._connection:
            self._release_lease_locked()
            self._lease_identity = (host_instance_id, host_generation)
            self._lease_token = uuid4().hex
            self._heartbeat_locked(time.time())

    def _migrate_locked(self) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(operation_history)"
            ).fetchall()
        }
        additions = {
            "argument_digest": "TEXT NOT NULL DEFAULT ''",
            "session_policy": (
                "TEXT NOT NULL DEFAULT 'principal_bound'"
            ),
            "recovery_json": "TEXT NOT NULL DEFAULT '{}'",
            "journal_name": "TEXT",
            "journal_device": "INTEGER",
            "journal_inode": "INTEGER",
        }
        for name, declaration in additions.items():
            if name not in columns:
                self._connection.execute(
                    f"ALTER TABLE operation_history ADD COLUMN {name} {declaration}"
                )

    def _start_lease(self) -> None:
        with self._lock, self._connection:
            self._heartbeat_locked(time.time())
        self._lease_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="hocuspocus-operation-lease",
            daemon=True,
        )
        self._lease_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._lease_stop.wait(HOST_HEARTBEAT_SECONDS):
            try:
                with self._lock, self._connection:
                    self._heartbeat_locked(time.time())
            except Exception:
                pass

    def _heartbeat_locked(self, now: float) -> None:
        if self._lease_identity is None:
            return
        instance_id, generation = self._lease_identity
        self._connection.execute(
            """INSERT INTO operation_host_leases VALUES (?, ?, ?, ?)
               ON CONFLICT(host_instance_id, host_generation) DO UPDATE SET
               lease_token = excluded.lease_token,
               heartbeat_at = excluded.heartbeat_at""",
            (instance_id, generation, self._lease_token, now),
        )

    def _release_lease_locked(self) -> None:
        if self._lease_identity is None:
            return
        instance_id, generation = self._lease_identity
        try:
            with self._connection:
                self._connection.execute(
                    """DELETE FROM operation_host_leases
                       WHERE host_instance_id = ? AND host_generation = ?
                       AND lease_token = ?""",
                    (instance_id, generation, self._lease_token),
                )
                self._reclaim_journals_locked(
                    time.time(), owned_token=self._lease_token
                )
        except sqlite3.Error:
            pass

    def _reserve_journal(
        self,
        principal_id: str,
        operation_id: str,
        tool_name: str,
        arguments_digest: str,
    ) -> JournalIdentity:
        with self._journal_platform.namespace_lock():
            self._reclaim_journals_namespace_locked(time.time())
            if self._journal_over_capacity:
                raise OSError("terminal journal scan bound is exhausted")
            count, size = self._journal_usage_namespace_locked()
            if (
                count >= JOURNAL_MAX_FILES
                or size + JOURNAL_SLOT_BYTES > JOURNAL_MAX_BYTES
            ):
                raise OSError("terminal journal capacity is exhausted")
            name = sha256(
                f"{principal_id}\0{operation_id}".encode("utf-8")
            ).hexdigest() + ".slot"
            slot = self._journal_platform.materialize(name)
            self._journal_platform.publish(
                slot,
                {
                    "kind": "armed",
                    "principalId": principal_id,
                    "operationId": operation_id,
                    "toolName": tool_name,
                    "argumentDigest": arguments_digest,
                    "createdAt": time.time(),
                    "ownerHostInstanceId": (
                        self._lease_identity[0] if self._lease_identity else None
                    ),
                    "ownerHostGeneration": (
                        self._lease_identity[1] if self._lease_identity else None
                    ),
                    "ownerLeaseToken": self._lease_token,
                    "fileDevice": slot.device,
                    "fileInode": slot.inode,
                },
            )
            self._journal_platform.flush_namespace()
            return slot

    def _write_journal(
        self,
        name: str,
        payload: dict[str, Any],
        expected_device: int,
        expected_inode: int,
    ) -> None:
        with self._journal_platform.namespace_lock():
            self._journal_platform.publish(
                JournalIdentity(name, expected_device, expected_inode), payload
            )

    def _read_journal(
        self,
        path: Path,
        expected_device: int | None = None,
        expected_inode: int | None = None,
    ) -> dict[str, Any] | None:
        expected = None
        if expected_device is not None and expected_inode is not None:
            expected = JournalIdentity(path.name, expected_device, expected_inode)
        with self._journal_platform.namespace_lock():
            return self._journal_platform.read(path, expected)

    def _remove_journal(self, name: str | None) -> None:
        if not name:
            return
        try:
            with self._journal_platform.namespace_lock():
                self._journal_platform.remove(name)
        except OSError:
            pass

    def _remove_journal_namespace_locked(self, name: str) -> None:
        try:
            self._journal_platform.remove(name)
        except OSError:
            pass

    def _recover_journals_locked(self) -> None:
        with self._journal_platform.namespace_lock():
            self._reclaim_journals_namespace_locked(time.time())

    def _scan_journal_paths_namespace_locked(self) -> list[Path]:
        paths, overflow = self._journal_platform.scan(JOURNAL_SCAN_LIMIT)
        self._journal_over_capacity = overflow
        return paths

    def _journal_usage_namespace_locked(self) -> tuple[int, int]:
        paths = self._scan_journal_paths_namespace_locked()
        if self._journal_over_capacity:
            raise OSError("terminal journal directory exceeds its hard bound")
        size = sum(path.stat(follow_symlinks=False).st_size for path in paths)
        return len(paths), size

    def _reclaim_journals_locked(
        self, now: float, *, owned_token: str | None = None
    ) -> None:
        with self._journal_platform.namespace_lock():
            self._reclaim_journals_namespace_locked(
                now, owned_token=owned_token
            )

    def _reclaim_journals_namespace_locked(
        self, now: float, *, owned_token: str | None = None
    ) -> None:
        for path in self._scan_journal_paths_namespace_locked():
            payload = self._journal_platform.read(path)
            if not isinstance(payload, dict):
                self._remove_journal_namespace_locked(path.name)
                continue
            row = self._row(
                str(payload.get("principalId", "")),
                str(payload.get("operationId", "")),
            )
            if row is None:
                if (
                    (
                        owned_token is not None
                        and payload.get("ownerLeaseToken") == owned_token
                    )
                    or self._orphan_is_stale(payload, now)
                ):
                    self._remove_journal_namespace_locked(path.name)
                continue
            if not _journal_matches(row, payload):
                self._remove_journal_namespace_locked(path.name)
                continue
            if row["state"] != "pending":
                self._remove_journal_namespace_locked(path.name)
                continue
            record = payload.get("record")
            if payload.get("kind") != "terminal" or not isinstance(record, dict):
                continue
            self._restore_terminal_locked(row, record)

    def _orphan_is_stale(self, payload: dict[str, Any], now: float) -> bool:
        lease = self._connection.execute(
            """SELECT lease_token, heartbeat_at FROM operation_host_leases
               WHERE host_instance_id = ? AND host_generation = ?""",
            (
                payload.get("ownerHostInstanceId"),
                payload.get("ownerHostGeneration"),
            ),
        ).fetchone()
        if (
            lease is not None
            and lease["lease_token"] == payload.get("ownerLeaseToken")
            and float(lease["heartbeat_at"]) >= now - HOST_LEASE_SECONDS
        ):
            return False
        created_at = payload.get("createdAt")
        return (
            type(created_at) not in {int, float}
            or float(created_at) <= now - JOURNAL_ORPHAN_GRACE_SECONDS
        )

    def _restore_terminal_locked(
        self, row: sqlite3.Row, record: dict[str, Any]
    ) -> None:
        result_json = _canonical_json(record.get("terminalResult"))
        error_json = _canonical_json(record.get("terminalError"))
        if record.get("terminalResult") is None:
            result_json = None
        if record.get("terminalError") is None:
            error_json = None
        byte_length = len((result_json or "").encode("utf-8")) + len(
            (error_json or "").encode("utf-8")
        )
        self._connection.execute(
            """UPDATE operation_history SET state = ?, finished_at = ?,
               delivery_stage = ?, commit_state = ?, result_json = ?,
               error_json = ?, recovery_json = '{}', journal_name = NULL,
               journal_device = NULL, journal_inode = NULL,
               byte_length = ? WHERE principal_id = ? AND operation_id = ?
               AND state = 'pending'""",
            (
                record["state"], record["finishedAt"],
                record["deliveryStage"], record["commitState"],
                result_json, error_json, byte_length,
                row["principal_id"], row["operation_id"],
            ),
        )

    def admit(
        self,
        operation_id: str,
        tool_name: str,
        principal_id: str,
        session_id: str | None,
        host_instance_id: str,
        host_generation: int,
        arguments_digest: str,
        session_policy: str = SESSION_POLICY_PRINCIPAL,
        durable_required: bool = False,
    ) -> tuple[str, dict[str, Any] | None]:
        with self._lock, self._connection:
            now = time.time()
            self._heartbeat_locked(now)
            self._prune_locked(now)
            row = self._row(principal_id, operation_id)
            if row is not None:
                if self._admission_collides(
                    row,
                    tool_name,
                    arguments_digest,
                    session_id,
                    session_policy,
                ):
                    return "collision", None
                if row["state"] == "pending":
                    journal_record = self._pending_journal_record(row)
                    if journal_record is not None:
                        self._restore_journal_best_effort(
                            row, journal_record
                        )
                        return "terminal", journal_record
                    if _belongs_to_host(
                        row, host_instance_id, host_generation
                    ) or self._owner_is_live_locked(row, now):
                        return "pending", self._public(row)
                    row = self._mark_unknown_locked(row)
                    return "terminal", self._public(row)
                return "terminal", self._public(row)
            if not self._make_admission_room_locked():
                return "capacity", None
            recovery = _canonical_json(_recovery_error())
            journal_slot = None
            if durable_required:
                try:
                    journal_slot = self._reserve_journal(
                        principal_id, operation_id, tool_name, arguments_digest
                    )
                except OSError:
                    return "capacity", None
            try:
                self._connection.execute(
                    """INSERT INTO operation_history (
                           principal_id, operation_id, tool_name, session_id,
                           host_instance_id, host_generation, argument_digest,
                           session_policy, state, admitted_at, finished_at,
                           delivery_stage, commit_state, result_json, error_json,
                           recovery_json, journal_name, journal_device,
                           journal_inode, byte_length
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL,
                         'admitted', 'unknown', NULL, NULL, ?, ?, ?, ?, ?)""",
                    (
                        principal_id, operation_id, tool_name, session_id,
                        host_instance_id, host_generation, arguments_digest,
                        session_policy, now, recovery,
                        journal_slot.name if journal_slot else None,
                        journal_slot.device if journal_slot else None,
                        journal_slot.inode if journal_slot else None,
                        len(recovery.encode("utf-8")),
                    ),
                )
            except Exception:
                self._remove_journal(
                    journal_slot.name if journal_slot else None
                )
                raise
            return "new", None

    @staticmethod
    def _admission_collides(
        row: sqlite3.Row,
        tool_name: str,
        arguments_digest: str,
        session_id: str | None,
        session_policy: str,
    ) -> bool:
        return (
            row["tool_name"] != tool_name
            or row["argument_digest"] != arguments_digest
            or row["session_policy"] != session_policy
            or (
                session_policy == "session_bound"
                and row["session_id"] != session_id
            )
        )

    def _owner_is_live_locked(self, row: sqlite3.Row, now: float) -> bool:
        lease = self._connection.execute(
            """SELECT heartbeat_at FROM operation_host_leases
               WHERE host_instance_id = ? AND host_generation = ?""",
            (row["host_instance_id"], row["host_generation"]),
        ).fetchone()
        return (
            lease is not None
            and float(lease["heartbeat_at"]) >= now - HOST_LEASE_SECONDS
        )

    def finish(
        self,
        operation_id: str,
        *,
        principal_id: str,
        commit_state: str,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        prepared = _prepare_terminal(commit_state, result, error)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM operation_history WHERE principal_id = ? "
                "AND operation_id = ? AND state = 'pending'",
                (principal_id, operation_id),
            ).fetchone()
            if row is None:
                return None
            journal_name = row["journal_name"]
            delivery_stage = "terminal"
            journal_record = _prepared_record(row, prepared, delivery_stage)
            journal_ready = False
            if journal_name:
                delivery_stage = "terminal_journaled"
                journal_record = _prepared_record(
                    row, prepared, delivery_stage
                )
                try:
                    self._write_journal(
                        journal_name,
                        {
                            "kind": "terminal",
                            "principalId": row["principal_id"],
                            "operationId": row["operation_id"],
                            "toolName": row["tool_name"],
                            "argumentDigest": row["argument_digest"],
                            "createdAt": row["admitted_at"],
                            "ownerHostInstanceId": row["host_instance_id"],
                            "ownerHostGeneration": row["host_generation"],
                            "ownerLeaseToken": self._lease_token,
                            "fileDevice": row["journal_device"],
                            "fileInode": row["journal_inode"],
                            "record": journal_record,
                        },
                        row["journal_device"],
                        row["journal_inode"],
                    )
                    journal_ready = True
                except Exception:
                    delivery_stage = "terminal"
                    journal_record = _prepared_record(
                        row, prepared, delivery_stage
                    )
            try:
                with self._connection:
                    self._write_terminal_locked(
                        row, prepared, delivery_stage
                    )
            except Exception:
                if not self._fallback_write_terminal(
                    row, prepared, delivery_stage
                ):
                    if journal_ready:
                        return journal_record
                    return _ephemeral_terminal(row, prepared)
            try:
                with self._connection:
                    self._prune_locked(time.time())
            except Exception:
                pass
            self._remove_journal(journal_name)
            return journal_record

    def _write_terminal_locked(
        self,
        row: sqlite3.Row,
        prepared: _PreparedTerminal,
        delivery_stage: str,
    ) -> None:
        self._connection.execute(
            """UPDATE operation_history SET state = ?, finished_at = ?,
               delivery_stage = ?, commit_state = ?,
               result_json = ?, error_json = ?, recovery_json = '{}',
               journal_name = NULL, journal_device = NULL,
               journal_inode = NULL, byte_length = ? WHERE principal_id = ?
               AND operation_id = ? AND state = 'pending'""",
            (
                prepared.state, prepared.finished_at, delivery_stage,
                prepared.commit_state,
                prepared.result_json, prepared.error_json,
                prepared.byte_length, row["principal_id"], row["operation_id"],
            ),
        )

    def _fallback_write_terminal(
        self,
        row: sqlite3.Row,
        prepared: _PreparedTerminal,
        delivery_stage: str,
    ) -> bool:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self._path, timeout=5.0)
            with connection:
                connection.execute(
                    """UPDATE operation_history SET state = ?, finished_at = ?,
                       delivery_stage = ?, commit_state = ?,
                       result_json = ?, error_json = ?, recovery_json = '{}',
                       journal_name = NULL, journal_device = NULL,
                       journal_inode = NULL, byte_length = ? WHERE principal_id = ?
                       AND operation_id = ? AND state = 'pending'""",
                    (
                        prepared.state, prepared.finished_at,
                        delivery_stage, prepared.commit_state,
                        prepared.result_json, prepared.error_json,
                        prepared.byte_length, row["principal_id"],
                        row["operation_id"],
                    ),
                )
            return True
        except Exception:
            return False
        finally:
            if connection is not None:
                connection.close()

    def lookup(
        self,
        operation_id: str,
        principal_id: str,
        *,
        host_instance_id: str | None = None,
        host_generation: int | None = None,
    ) -> dict[str, Any] | None:
        with self._lock, self._connection:
            now = time.time()
            self._heartbeat_locked(now)
            self._prune_locked(now)
            row = self._row(principal_id, operation_id)
            if row is not None and row["state"] == "pending":
                journal_record = self._pending_journal_record(row)
                if journal_record is not None:
                    self._restore_journal_best_effort(row, journal_record)
                    return journal_record
            if (
                row is not None
                and row["state"] == "pending"
                and host_instance_id is not None
                and host_generation is not None
                and not _belongs_to_host(row, host_instance_id, host_generation)
                and not self._owner_is_live_locked(row, now)
            ):
                row = self._mark_unknown_locked(row)
            return self._public(row) if row is not None else None

    def _pending_journal_record(
        self, row: sqlite3.Row
    ) -> dict[str, Any] | None:
        name = row["journal_name"]
        if not name:
            return None
        payload = self._read_journal(
            self._journal_dir / name,
            row["journal_device"],
            row["journal_inode"],
        )
        if (
            not isinstance(payload, dict)
            or payload.get("kind") != "terminal"
            or not _journal_matches(row, payload)
        ):
            return None
        record = payload.get("record")
        return record if isinstance(record, dict) else None

    def _restore_journal_best_effort(
        self, row: sqlite3.Row, record: dict[str, Any]
    ) -> None:
        try:
            self._restore_terminal_locked(row, record)
            self._connection.commit()
            self._remove_journal(row["journal_name"])
        except Exception:
            try:
                self._connection.rollback()
            except sqlite3.Error:
                pass

    def _mark_unknown_locked(self, row: sqlite3.Row) -> sqlite3.Row:
        recovery = _canonical_json(_recovery_error())
        if row["recovery_json"] not in {None, "", "{}"}:
            recovery = row["recovery_json"]
        self._connection.execute(
            """UPDATE operation_history SET state = 'unknown',
               finished_at = ?, delivery_stage = 'host_restarted',
               commit_state = 'partial_or_unknown', error_json = ?,
               byte_length = ? WHERE principal_id = ? AND operation_id = ?
               AND state = 'pending'""",
            (
                time.time(), recovery, len(recovery.encode("utf-8")),
                row["principal_id"], row["operation_id"],
            ),
        )
        return self._row(row["principal_id"], row["operation_id"])

    def _row(self, principal_id: str, operation_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM operation_history WHERE principal_id = ? "
            "AND operation_id = ?", (principal_id, operation_id),
        ).fetchone()

    def _prune_locked(self, now: float) -> None:
        cutoff = now - RETENTION_SECONDS
        self._connection.execute(
            """DELETE FROM operation_history WHERE finished_at < ?
               AND commit_state != 'partial_or_unknown'""", (cutoff,)
        )
        self._connection.execute(
            "DELETE FROM operation_host_leases WHERE heartbeat_at < ?",
            (now - HOST_LEASE_SECONDS * 4,),
        )
        self._prune_capacity_locked()

    def _prune_capacity_locked(self) -> None:
        while True:
            count, size = self._connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(byte_length), 0) "
                "FROM operation_history"
            ).fetchone()
            if int(count) <= MAX_RECORDS and int(size) <= MAX_BYTES:
                return
            candidate = self._connection.execute(
                """SELECT principal_id, operation_id FROM operation_history
                   WHERE state != 'pending'
                   AND commit_state != 'partial_or_unknown'
                   ORDER BY finished_at ASC LIMIT 1"""
            ).fetchone()
            if candidate is None:
                return
            key = (candidate["principal_id"], candidate["operation_id"])
            self._connection.execute(
                "DELETE FROM operation_history WHERE principal_id = ? "
                "AND operation_id = ?", key,
            )

    def _make_admission_room_locked(self) -> bool:
        while True:
            count, reserved = self._connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(CASE WHEN state = 'pending' "
                "THEN ? ELSE byte_length END), 0) FROM operation_history",
                (MAX_RECORD_BYTES,),
            ).fetchone()
            if int(count) < MAX_RECORDS and (
                int(reserved) + MAX_RECORD_BYTES <= MAX_BYTES
            ):
                return True
            candidate = self._connection.execute(
                """SELECT principal_id, operation_id FROM operation_history
                   WHERE state != 'pending'
                   AND commit_state != 'partial_or_unknown'
                   ORDER BY finished_at ASC LIMIT 1"""
            ).fetchone()
            if candidate is None:
                return False
            key = (candidate["principal_id"], candidate["operation_id"])
            self._connection.execute(
                "DELETE FROM operation_history WHERE principal_id = ? "
                "AND operation_id = ?", key,
            )

    def _public(self, row: sqlite3.Row) -> dict[str, Any]:
        result = _decode(row["result_json"])
        error = _decode(row["error_json"])
        return {
            "operationId": row["operation_id"],
            "toolName": row["tool_name"],
            "hostInstanceId": row["host_instance_id"],
            "hostGeneration": row["host_generation"],
            "argumentDigest": row["argument_digest"],
            "sessionPolicy": row["session_policy"],
            "state": row["state"],
            "deliveryStage": row["delivery_stage"],
            "commitState": row["commit_state"],
            "admittedAt": row["admitted_at"],
            "finishedAt": row["finished_at"],
            "terminalResult": copy.deepcopy(result),
            "terminalError": copy.deepcopy(error),
        }


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 16:
        return "<omitted>"
    if isinstance(value, dict):
        output = {}
        for key, item in list(value.items())[:4096]:
            lowered = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if lowered == "content" and isinstance(item, (dict, list, tuple)):
                output[str(key)] = _sanitize(item, depth + 1)
            elif lowered in _SENSITIVE_KEYS:
                output[str(key)] = "<redacted>"
            else:
                output[str(key)] = _sanitize(item, depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in list(value)[:4096]]
    if isinstance(value, str):
        if len(value) > 4096:
            return "<redacted>"
        if not _HOUDINI_PATH.match(value) and _PHYSICAL_PATH.search(value):
            return "<redacted>"
        return value
    return value if value is None or type(value) in {bool, int, float} else str(value)


def _sanitize_error(error: dict[str, Any] | None) -> dict[str, Any] | None:
    if error is None:
        return None
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    safe_data = _sanitize(data)
    return {
        "code": int(error.get("code", -32603)),
        "message": "Terminal operation failed.",
        "data": safe_data,
    }


def sanitize_terminal_payload(value: Any) -> Any:
    return _sanitize(value)


def sanitize_terminal_error(
    error: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _sanitize_error(error)


def _prepare_terminal(
    commit_state: str,
    result: dict[str, Any] | None,
    error: dict[str, Any] | None,
) -> _PreparedTerminal:
    safe_result = _sanitize(result)
    safe_error = _sanitize_error(error)
    result_json = _canonical_json(safe_result) if result is not None else None
    error_json = _canonical_json(safe_error) if error is not None else None
    byte_length = len((result_json or "").encode("utf-8")) + len(
        (error_json or "").encode("utf-8")
    )
    if byte_length > MAX_RECORD_BYTES:
        if error is None:
            result_json = _canonical_json(_oversize_result(safe_result))
            error_json = None
        else:
            result_json = None
            error_json = _canonical_json(_oversize_error())
        byte_length = len((result_json or error_json or "").encode("utf-8"))
    return _PreparedTerminal(
        state="succeeded" if error is None else "failed",
        commit_state=commit_state,
        finished_at=time.time(),
        result_json=result_json,
        error_json=error_json,
        byte_length=byte_length,
    )


def _oversize_result(result: Any) -> dict[str, Any]:
    metadata = result.get("_meta", {}) if isinstance(result, dict) else {}
    return {
        "content": [{
            "type": "text",
            "text": "Operation completed; its retained receipt exceeded the limit.",
        }],
        "structuredContent": {
            "completed": True,
            "receiptOmitted": True,
        },
        "_meta": metadata,
    }


def _ephemeral_terminal(
    row: sqlite3.Row, prepared: _PreparedTerminal
) -> dict[str, Any]:
    record = _prepared_record(row, prepared, "terminal_unpersisted")
    result = record["terminalResult"]
    if isinstance(result, dict):
        metadata = result.setdefault("_meta", {})
        operation = metadata.get("hocuspocus/operation")
        if isinstance(operation, dict):
            operation["deliveryStage"] = "terminal_unpersisted"
            operation["reconciliationDurable"] = False
    return record


def _prepared_record(
    row: sqlite3.Row,
    prepared: _PreparedTerminal,
    delivery_stage: str,
) -> dict[str, Any]:
    return {
        "operationId": row["operation_id"],
        "toolName": row["tool_name"],
        "hostInstanceId": row["host_instance_id"],
        "hostGeneration": row["host_generation"],
        "argumentDigest": row["argument_digest"],
        "sessionPolicy": row["session_policy"],
        "state": prepared.state,
        "deliveryStage": delivery_stage,
        "commitState": prepared.commit_state,
        "admittedAt": row["admitted_at"],
        "finishedAt": prepared.finished_at,
        "terminalResult": _decode(prepared.result_json),
        "terminalError": _decode(prepared.error_json),
    }


def _recovery_error() -> dict[str, Any]:
    return {
        "code": -32099,
        "message": "Host restarted before the operation outcome was recorded.",
        "data": {
            "hocusCode": "HOCUS999", "kind": "operation_outcome_unknown",
            "retryable": False,
        },
    }


def _oversize_error() -> dict[str, Any]:
    return {
        "code": -32603,
        "message": "Terminal operation payload exceeded reconciliation storage.",
        "data": {"retryable": False},
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def _decode(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _belongs_to_host(
    row: sqlite3.Row, host_instance_id: str, host_generation: int
) -> bool:
    return (
        row["host_instance_id"] == host_instance_id
        and int(row["host_generation"]) == host_generation
    )


def _journal_matches(row: sqlite3.Row, payload: dict[str, Any]) -> bool:
    if (
        payload.get("principalId") != row["principal_id"]
        or payload.get("operationId") != row["operation_id"]
        or payload.get("toolName") != row["tool_name"]
        or payload.get("argumentDigest") != row["argument_digest"]
        or payload.get("fileDevice") != row["journal_device"]
        or payload.get("fileInode") != row["journal_inode"]
    ):
        return False
    record = payload.get("record")
    if payload.get("kind") != "terminal":
        return payload.get("kind") == "armed"
    return (
        isinstance(record, dict)
        and record.get("operationId") == row["operation_id"]
        and record.get("toolName") == row["tool_name"]
        and record.get("argumentDigest") == row["argument_digest"]
        and record.get("hostInstanceId") == row["host_instance_id"]
        and record.get("hostGeneration") == row["host_generation"]
        and record.get("sessionPolicy") == row["session_policy"]
        and record.get("state") in {"succeeded", "failed"}
        and record.get("commitState") in {
            "committed", "not_committed", "not_applicable",
            "partial_or_unknown",
        }
    )


__all__ = [
    "HOST_LEASE_SECONDS", "OperationHistory", "RETENTION_SECONDS",
    "SESSION_POLICY_PRINCIPAL", "argument_digest", "attach_operation_metadata",
    "commit_state_for_result", "error_from_terminal", "new_operation_id",
    "sanitize_terminal_error", "sanitize_terminal_payload", "valid_operation_id",
]
