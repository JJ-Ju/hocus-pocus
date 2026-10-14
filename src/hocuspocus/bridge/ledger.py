"""The bridge ledger: instances, jobs and launches in SQLite (spec-2.0 §3; BIBLE §3.3, §7).

``<state_dir>/ledger.sqlite`` (WAL) remembers what the registry forgets: every Houdini the
bridge has seen (its name, role and last hip, kept after it exits so ``houdini_status``
can list it under ``recent``), every job it saw start (an opaque short id such as
``j7f3a9`` mapped to the host's ``<pid>-<hostid>``, the last status, and the result once
fetched) and every launch. It survives a bridge restart; on start the bridge reconciles it
with the registry and marks the instances that are gone.

One connection per bridge, serialised by a lock (one writer per bridge; bridges sharing a
state dir share the file, and SQLite's WAL locking orders their writes). The ledger is a
memory, never an authority: the registry says what is live and a host says what its jobs
are doing. Every method swallows ``sqlite3`` errors (logged): a broken ledger must never
fail a tool call. A file that cannot be opened falls back to an in-memory ledger.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from ..tools import paths

log = logging.getLogger(__name__)

LEDGER_FILE = "ledger.sqlite"
JOBS_DIR = "jobs"
SCHEMA_VERSION = 1
SPILL_BYTES = 16 * 1024
"""A job result larger than this (serialised) goes to ``<state_dir>/jobs/<id>.json``."""
ROLES: tuple[str, ...] = ("editor", "worker")
RECENT_MAX = 5
"""How many dead instances ``houdini_status.recent`` lists, newest first."""
JOBS_MAX = 500
"""Finished job rows kept; older ones (and their spill files) are pruned."""
OBSERVE_REFRESH_S = 30.0
"""An unchanged live instance's ``last_seen`` is rewritten at most this often."""
JOB_ID_RE = re.compile(r"^j[0-9a-f]{5,12}$")
"""A ledger job id: ``j`` and hex digits. Host ids are ``<pid>-<hex>`` or bare hex, so the
two never collide."""
STATUS_KEYS = (
    "job_id", "tool", "label", "state", "progress", "current", "total", "message",
    "elapsed_s", "started", "nodes",
)  # fmt: skip
"""The keys of a host job snapshot the ledger keeps as the job's last status."""

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS instances ("
    " pid INTEGER PRIMARY KEY, name TEXT, role TEXT, label TEXT, ui INTEGER, hip TEXT,"
    " started TEXT, last_seen REAL, launched_by INTEGER, houdini TEXT,"
    " alive INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS jobs ("
    " id TEXT PRIMARY KEY, host_id TEXT UNIQUE NOT NULL, instance_pid INTEGER, tool TEXT,"
    " state TEXT, progress REAL, message TEXT, started TEXT, finished TEXT,"
    " result_path TEXT, result TEXT, status TEXT, updated REAL)",
    "CREATE INDEX IF NOT EXISTS jobs_by_pid ON jobs (instance_pid)",
    "CREATE TABLE IF NOT EXISTS launches ("
    " pid INTEGER, argv TEXT, work_dir TEXT, time REAL, mode TEXT)",
)


def default_role(ui: bool) -> str:
    """``editor`` for a GUI Houdini, ``worker`` for a headless one (spec-2.0 §3)."""
    return "editor" if ui else "worker"


def is_ledger_id(job_id: Any) -> bool:
    return isinstance(job_id, str) and JOB_ID_RE.match(job_id) is not None


LEDGER_FORM_RE = re.compile(r"^j[0-9A-Za-z]+$")
"""What a caller who means a ledger id writes: ``j`` and letters or digits, no ``-``. A host
id is ``<pid>-<hex>`` (or its bare hex, which never starts with ``j``)."""


def looks_like_ledger_id(job_id: Any) -> bool:
    """Whether ``job_id`` has the ledger's form (``jzzzz`` too), so a miss is answered
    about the ledger rather than about the 1.x ``<pid>-<id>`` ids (review 25 papercut 5)."""
    return isinstance(job_id, str) and LEDGER_FORM_RE.match(job_id) is not None


def _iso(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _loads(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


class Ledger:
    """The SQLite ledger. ``path=None`` keeps it in memory (unit tests, fake bridges)."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        jobs_dir: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.jobs_dir = Path(jobs_dir) if jobs_dir is not None else None
        self.clock = clock
        self._lock = threading.RLock()
        self._observed: dict[int, tuple[tuple[Any, ...], float]] = {}
        self._reconciled = False
        self._conn = self._open()

    @classmethod
    def at(cls, state_dir: Path | None = None, **kwargs: Any) -> Ledger:
        """The ledger of ``state_dir`` (default :func:`paths.state_dir`)."""
        state = state_dir if state_dir is not None else paths.state_dir()
        return cls(state / LEDGER_FILE, jobs_dir=state / JOBS_DIR, **kwargs)

    # -- connection ---------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        if self.path is not None:
            try:
                paths.ensure_private_dir(self.path.parent)
                conn = self._connect(str(self.path))
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._migrate(conn)
                return conn
            except (OSError, sqlite3.Error) as exc:
                log.warning("ledger %s unusable (%s); keeping it in memory", self.path, exc)
                self.path = None
                self.jobs_dir = None
        conn = self._connect(":memory:")
        self._migrate(conn)
        return conn

    @staticmethod
    def _connect(target: str) -> sqlite3.Connection:
        conn = sqlite3.connect(target, timeout=5.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        for statement in _SCHEMA:
            conn.execute(statement)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', ?)", (str(SCHEMA_VERSION),)
        )

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        try:
            with self._lock:
                return list(self._conn.execute(sql, tuple(params)))
        except sqlite3.Error as exc:
            log.warning("ledger read failed: %s", exc)
            return []

    def _write(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        try:
            with self._tx() as conn:
                return fn(conn)
        except sqlite3.Error as exc:
            log.warning("ledger write failed: %s", exc)
            return None

    def close(self) -> None:
        with self._lock, contextlib.suppress(sqlite3.Error):
            self._conn.close()

    @property
    def journal_mode(self) -> str:
        rows = self._rows("PRAGMA journal_mode")
        return str(rows[0][0]) if rows else ""

    # -- instances ----------------------------------------------------------------------

    def observe(self, live: Iterable[Any], *, reconcile: bool = False) -> None:
        """Record the live registry entries (``bridge.instances.Instance``) and, with
        ``reconcile``, mark every remembered instance not among them dead. Writes only what
        changed (and refreshes ``last_seen`` every :data:`OBSERVE_REFRESH_S`)."""
        now = self.clock()
        pending = []
        for inst in live:
            key = (inst.started, inst.label, inst.ui, inst.hip, inst.name, inst.houdini)
            seen = self._observed.get(inst.pid)
            if not reconcile and seen and seen[0] == key and now - seen[1] < OBSERVE_REFRESH_S:
                continue
            pending.append((inst, key))
        live_pids = {inst.pid for inst in live} if reconcile else set()
        if not pending and (
            not reconcile or (self._reconciled and live_pids == set(self._observed))
        ):
            return

        def write(conn: sqlite3.Connection) -> bool:
            for inst, _key in pending:
                row = conn.execute(
                    "SELECT started FROM instances WHERE pid = ?", (inst.pid,)
                ).fetchone()
                if row is not None and row["started"] not in (None, "", inst.started):
                    # The pid was reused by another process: forget the old one's role.
                    conn.execute("DELETE FROM instances WHERE pid = ?", (inst.pid,))
                    row = None
                values = (
                    inst.name or None,
                    inst.label,
                    int(inst.ui),
                    inst.hip,
                    inst.started,
                    now,
                    inst.launched_by,
                    inst.houdini,
                    inst.pid,
                )
                if row is None:
                    conn.execute(
                        "INSERT INTO instances (name, label, ui, hip, started, last_seen,"
                        " launched_by, houdini, pid, alive) VALUES (?,?,?,?,?,?,?,?,?,1)",
                        values,
                    )
                else:
                    conn.execute(
                        "UPDATE instances SET name = ?, label = ?, ui = ?, hip = ?, started = ?,"
                        " last_seen = ?, launched_by = ?, houdini = ?, alive = 1 WHERE pid = ?",
                        values,
                    )
                if inst.name:
                    conn.execute(
                        "UPDATE instances SET name = NULL WHERE name = ? AND pid != ?",
                        (inst.name, inst.pid),
                    )
            if reconcile:
                marks = ",".join("?" * len(live_pids))
                where = f"alive = 1 AND pid NOT IN ({marks})" if live_pids else "alive = 1"
                conn.execute(f"UPDATE instances SET alive = 0 WHERE {where}", tuple(live_pids))
            return True

        if not self._write(write):
            return
        for inst, key in pending:
            self._observed[inst.pid] = (key, now)
        if reconcile:
            for pid in list(self._observed):
                if pid not in live_pids:
                    self._observed.pop(pid, None)
            self._reconciled = True

    def mark_dead(self, pid: int, *, hip: str | None = None) -> None:
        """An instance has exited (or was quit): keep it for ``recent``."""
        self._observed.pop(pid, None)
        now = self.clock()

        def write(conn: sqlite3.Connection) -> None:
            conn.execute("UPDATE instances SET alive = 0, last_seen = ? WHERE pid = ?", (now, pid))
            if hip:
                conn.execute("UPDATE instances SET hip = ? WHERE pid = ?", (hip, pid))

        self._write(write)

    def set_role(self, pid: int, role: str) -> None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, not {role!r}")
        self._ensure(pid)
        self._write(
            lambda conn: conn.execute("UPDATE instances SET role = ? WHERE pid = ?", (role, pid))
        )

    def set_name(self, pid: int, name: str) -> None:
        """Store ``name`` on ``pid`` (moving it from any other instance); ``""`` clears it."""
        self._ensure(pid)

        def write(conn: sqlite3.Connection) -> None:
            if name:
                conn.execute(
                    "UPDATE instances SET name = NULL WHERE name = ? AND pid != ?", (name, pid)
                )
            conn.execute("UPDATE instances SET name = ? WHERE pid = ?", (name or None, pid))

        self._write(write)
        self._observed.pop(pid, None)

    def _ensure(self, pid: int) -> None:
        self._write(
            lambda conn: conn.execute(
                "INSERT OR IGNORE INTO instances (pid, last_seen, alive) VALUES (?, ?, 1)",
                (pid, self.clock()),
            )
        )

    def role_of(self, pid: int, ui: bool) -> str:
        """The role set with ``houdini_connect {role}``, else :func:`default_role`."""
        rows = self._rows("SELECT role FROM instances WHERE pid = ?", (pid,))
        role = rows[0]["role"] if rows else None
        return role if role in ROLES else default_role(ui)

    def instance(self, pid: int) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM instances WHERE pid = ?", (pid,))
        return self._instance_row(rows[0]) if rows else None

    def find_name(self, name: str) -> dict[str, Any] | None:
        """The remembered instance last named ``name`` (live or not)."""
        rows = self._rows(
            "SELECT * FROM instances WHERE name = ? ORDER BY last_seen DESC LIMIT 1", (name,)
        )
        return self._instance_row(rows[0]) if rows else None

    def knows_pid(self, pid: int) -> bool:
        if self._rows("SELECT 1 FROM instances WHERE pid = ?", (pid,)):
            return True
        if self._rows("SELECT 1 FROM jobs WHERE instance_pid = ? LIMIT 1", (pid,)):
            return True
        return bool(self._rows("SELECT 1 FROM launches WHERE pid = ? LIMIT 1", (pid,)))

    def recent(self, limit: int = RECENT_MAX) -> list[dict[str, Any]]:
        """Dead-but-remembered instances, most recently seen first."""
        rows = self._rows(
            "SELECT * FROM instances WHERE alive = 0 AND started IS NOT NULL"
            " ORDER BY last_seen DESC LIMIT ?",
            (int(limit),),
        )
        return [self._instance_row(row) for row in rows]

    @staticmethod
    def _instance_row(row: sqlite3.Row) -> dict[str, Any]:
        ui = bool(row["ui"])
        out: dict[str, Any] = {
            "pid": row["pid"],
            "label": row["label"] or "",
            "ui": ui,
            "role": row["role"] if row["role"] in ROLES else default_role(ui),
            "hip": row["hip"] or "",
            "started": row["started"] or "",
            "last_seen": _iso(row["last_seen"]),
            "alive": bool(row["alive"]),
        }
        if row["name"]:
            out["name"] = row["name"]
        return out

    # -- jobs ---------------------------------------------------------------------------

    def _new_id(self, conn: sqlite3.Connection) -> str:
        for attempt in range(40):
            digits = 5 if attempt < 20 else 8
            candidate = "j" + secrets.token_hex(4)[:digits]
            if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (candidate,)).fetchone() is None:
                return candidate
        return "j" + secrets.token_hex(6)

    def record_job(self, pid: int, status: dict[str, Any]) -> str | None:
        """Record (or update) the job a host reported, keyed by its host id; returns the
        ledger id. ``status`` is a host job snapshot (``job_id``, ``state``, ...)."""
        host_id = status.get("job_id")
        if not isinstance(host_id, str) or not host_id or is_ledger_id(host_id):
            return None
        snapshot = {key: status[key] for key in STATUS_KEYS if key in status}
        state = snapshot.get("state") if isinstance(snapshot.get("state"), str) else None
        now = self.clock()
        progress = snapshot.get("progress")
        progress = (
            float(progress)
            if isinstance(progress, int | float) and not isinstance(progress, bool)
            else None
        )
        message = snapshot.get("message") if isinstance(snapshot.get("message"), str) else None

        def write(conn: sqlite3.Connection) -> str:
            row = conn.execute(
                "SELECT id, status, finished FROM jobs WHERE host_id = ?", (host_id,)
            ).fetchone()
            if row is None:
                job_id = self._new_id(conn)
                conn.execute(
                    "INSERT INTO jobs (id, host_id, instance_pid, tool, state, progress, message,"
                    " started, finished, status, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        host_id,
                        pid,
                        snapshot.get("tool"),
                        state or "running",
                        progress,
                        message,
                        snapshot.get("started") or _iso(now),
                        None if state in (None, "running") else _iso(now),
                        _dumps(snapshot),
                        now,
                    ),
                )
                self._prune(conn)
                return job_id
            merged = dict(_loads(row["status"]) or {})
            merged.update(snapshot)
            finished = row["finished"]
            if state not in (None, "running") and not finished:
                finished = _iso(now)
            conn.execute(
                "UPDATE jobs SET tool = COALESCE(?, tool), state = COALESCE(?, state),"
                " progress = COALESCE(?, progress), message = COALESCE(?, message),"
                " finished = ?, status = ?, updated = ? WHERE id = ?",
                (
                    snapshot.get("tool"),
                    state,
                    progress,
                    message,
                    finished,
                    _dumps(merged),
                    now,
                    row["id"],
                ),
            )
            return str(row["id"])

        return self._write(write)

    def store_result(self, host_id: str, result: Any) -> None:
        """Keep a finished job's result: inline, or spilled to ``jobs/<id>.json`` when its
        JSON is over :data:`SPILL_BYTES` (and the ledger has a state dir)."""
        text = _dumps(result)
        row = self._job_row(host_id)
        if row is None:
            return
        path: Path | None = None
        if len(text.encode("utf-8")) > SPILL_BYTES and self.jobs_dir is not None:
            path = self.jobs_dir / f"{row['id']}.json"
            try:
                paths.ensure_private_dir(self.jobs_dir)
                path.write_text(text, encoding="utf-8")
            except OSError as exc:
                log.warning("cannot spill job %s result: %s", row["id"], exc)
                path = None
        self._write(
            lambda conn: conn.execute(
                "UPDATE jobs SET result = ?, result_path = ? WHERE id = ?",
                (None if path else text, str(path) if path else None, row["id"]),
            )
        )

    def result(self, job_id: str) -> Any:
        """A stored result (loaded from its spill file if it was spilled), else None."""
        row = self._job_row(job_id)
        if row is None:
            return None
        if row["result_path"]:
            try:
                return json.loads(Path(row["result_path"]).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return _loads(row["result"])

    def _job_row(self, job_id: str) -> sqlite3.Row | None:
        column = "id" if is_ledger_id(job_id) else "host_id"
        rows = self._rows(f"SELECT * FROM jobs WHERE {column} = ?", (job_id,))
        return rows[0] if rows else None

    def job(self, job_id: str) -> dict[str, Any] | None:
        """``{id, host_id, pid, tool, state, ..., status, has_result}`` by either id."""
        row = self._job_row(job_id)
        return self._job_dict(row) if row is not None else None

    def to_host(self, job_id: str) -> tuple[int | None, str] | None:
        """``(pid, host id)`` for a ledger id; ``None`` when the ledger has no such job."""
        row = self._job_row(job_id) if is_ledger_id(job_id) else None
        return (row["instance_pid"], row["host_id"]) if row is not None else None

    def ledger_id(self, host_id: str) -> str | None:
        rows = self._rows("SELECT id FROM jobs WHERE host_id = ?", (host_id,))
        return str(rows[0]["id"]) if rows else None

    def last_status(self, job_id: str) -> dict[str, Any] | None:
        row = self._job_row(job_id)
        return _loads(row["status"]) if row is not None else None

    def jobs_snapshot(self, pid: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Every remembered job (or ``pid``'s), newest first: what ``houdini://jobs``
        serves. Each row: ``id, host_id, pid, tool, state, progress, message, started,
        finished, has_result`` and the last host status as ``status``."""
        where, params = ("WHERE instance_pid = ?", (pid,)) if pid is not None else ("", ())
        rows = self._rows(
            f"SELECT * FROM jobs {where} ORDER BY updated DESC LIMIT ?", (*params, int(limit))
        )
        return [self._job_dict(row) for row in rows]

    def running(self, pid: int) -> int:
        rows = self._rows(
            "SELECT COUNT(*) FROM jobs WHERE instance_pid = ? AND state = 'running'", (pid,)
        )
        return int(rows[0][0]) if rows else 0

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "host_id": row["host_id"],
            "pid": row["instance_pid"],
            "tool": row["tool"],
            "state": row["state"],
            "progress": row["progress"],
            "message": row["message"],
            "started": row["started"],
            "finished": row["finished"],
            "has_result": bool(row["result"] or row["result_path"]),
            "status": _loads(row["status"]) or {},
        }

    def _prune(self, conn: sqlite3.Connection) -> None:
        old = conn.execute(
            "SELECT id, result_path FROM jobs WHERE state != 'running'"
            " ORDER BY updated DESC LIMIT -1 OFFSET ?",
            (JOBS_MAX,),
        ).fetchall()
        for row in old:
            if row["result_path"]:
                with contextlib.suppress(OSError):
                    Path(row["result_path"]).unlink()
            conn.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))

    # -- launches -----------------------------------------------------------------------

    def record_launch(
        self, pid: int, argv: Iterable[str], work_dir: str | Path | None, mode: str = ""
    ) -> None:
        self._write(
            lambda conn: conn.execute(
                "INSERT INTO launches (pid, argv, work_dir, time, mode) VALUES (?,?,?,?,?)",
                (pid, _dumps(list(argv)), str(work_dir) if work_dir else None, self.clock(), mode),
            )
        )

    def launches(self, pid: int | None = None) -> list[dict[str, Any]]:
        where, params = ("WHERE pid = ?", (pid,)) if pid is not None else ("", ())
        rows = self._rows(f"SELECT * FROM launches {where} ORDER BY time DESC", params)
        return [
            {
                "pid": row["pid"],
                "argv": _loads(row["argv"]) or [],
                "work_dir": row["work_dir"],
                "time": _iso(row["time"]),
                "mode": row["mode"] or "",
            }
            for row in rows
        ]
