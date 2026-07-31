"""Verify every supported graph-store upgrade path and emit an external receipt."""

from __future__ import annotations

import argparse
import copy
import io
import json
import logging
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any

from release_evidence_support import ROOT, file_digest, receipt, write_receipt

from hocuspocus.live.graph_store import LiveGraphStore
from tests.test_runtime_scenarios import (
    RuntimeScenarios,
    _network_document,
    _persistent_plan,
)

FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "graph_store"
SUPPORTED_STARTS = {
    1: ("v1.sql",),
    2: ("v1.sql", "v2.sql"),
}
PRESERVED_TABLES = {
    1: ("documents", "document_versions", "apply_commits"),
    2: (
        "documents",
        "document_versions",
        "apply_commits",
        "apply_operation_audit",
    ),
}


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _construct(path: Path, fixture_names: tuple[str, ...]) -> None:
    with closing(sqlite3.connect(path)) as connection:
        for fixture_name in fixture_names:
            sql = (FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8")
            connection.executescript(sql)
        connection.commit()


def _prove_plan_commit_lifecycle(store: LiveGraphStore, version: int) -> bool:
    plan = _persistent_plan()
    plan_id = plan["planId"]
    commit_id = f"upgrade-v{version}-commit"
    request_id = f"upgrade-v{version}-request"
    store.store_immutable_plan(
        plan_id=plan_id,
        session_id=plan["sessionId"],
        root_path=plan["rootPath"],
        expires_at=plan["expiresAt"],
        created_at=plan["createdAt"],
        now=150.0,
        payload=plan,
    )
    pending = store.begin_plan_commit(
        plan_commit_id=commit_id,
        plan_id=plan_id,
        plan_hash=plan["planHash"],
        session_id=plan["sessionId"],
        idempotency_key=request_id,
        pre_apply_snapshot={"documentRevision": 4},
        inverse_plan={"operations": []},
        now=150.0,
    )
    replay = store.begin_plan_commit(
        plan_commit_id="ignored",
        plan_id=plan_id,
        plan_hash=plan["planHash"],
        session_id=plan["sessionId"],
        idempotency_key=request_id,
        pre_apply_snapshot={},
        inverse_plan=None,
        now=151.0,
    )
    committed = store.finish_plan_commit(
        plan_commit_id=commit_id,
        state="committed",
        result={"verified": True},
        error=None,
        now=160.0,
    )
    return (
        pending == replay
        and committed["state"] == "committed"
        and store.load_plan_commit(idempotency_key=request_id)["state"] == "committed"
    )


def _verify_start(version: int, fixture_names: tuple[str, ...]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / f"graph-store-v{version}.sqlite3"
        _construct(path, fixture_names)
        with closing(sqlite3.connect(path)) as connection:
            before = {
                table: _rows(connection, table)
                for table in PRESERVED_TABLES[version]
            }
            before_version = connection.execute("PRAGMA user_version").fetchone()[0]
        store = LiveGraphStore(logging.getLogger("release.graph-store"), db_path=path)
        document = store.get_document_by_id("fixture:/geo")
        if document != {"documentId": "fixture:/geo", "kind": "network"}:
            raise RuntimeError(f"v{version} document changed during upgrade.")
        first = store.upsert_document_from_live(
            _network_document(),
            live_revision=20 + version,
            source="release-upgrade-evidence",
        )
        changed = copy.deepcopy(_network_document())
        changed["nodes"][0]["flags"]["bypass"] = True
        second = store.upsert_document_from_live(
            changed,
            live_revision=21 + version,
            source="release-upgrade-evidence",
        )
        plan_commit_lifecycle = _prove_plan_commit_lifecycle(store, version)
        with closing(sqlite3.connect(path)) as connection:
            after = {
                table: _rows(connection, table)[: len(before[table])]
                for table in PRESERVED_TABLES[version]
            }
            current_version = connection.execute("PRAGMA user_version").fetchone()[0]
            migrations = _rows(connection, "graph_store_migrations")
            plan_tables = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name IN (
                        'immutable_apply_plans',
                        'plan_apply_commits',
                        'plan_commit_events'
                    )
                    ORDER BY name
                    """
                ).fetchall()
            ]
        preserved = before == after
        continued = second["documentRevision"] == first["documentRevision"] + 1
        passed = (
            before_version == version
            and current_version == 3
            and preserved
            and continued
            and plan_commit_lifecycle
            and [item["version"] for item in migrations] == [1, 2, 3]
            and len(plan_tables) == 3
        )
        return {
            "startingVersion": version,
            "currentVersion": current_version,
            "fixtures": list(fixture_names),
            "preservedTables": list(PRESERVED_TABLES[version]),
            "preserved": preserved,
            "migrationLedger": [
                {
                    "version": item["version"],
                    "name": item["name"],
                    "checksum": item["checksum"],
                }
                for item in migrations
            ],
            "continuedRevisionBehavior": continued,
            "continuedPlanCommitLifecycle": plan_commit_lifecycle,
            "currentPlanTables": plan_tables,
            "passed": passed,
        }


def _run_public_scenarios() -> dict[str, Any]:
    names = (
        "test_graph_store_upgrades_existing_documents_without_data_loss",
        "test_graph_store_persists_an_idempotent_plan_commit_lifecycle",
    )
    suite = unittest.TestSuite(RuntimeScenarios(name) for name in names)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    return {
        "scenarioNames": list(names),
        "testsRun": result.testsRun,
        "successful": result.wasSuccessful(),
        "failures": len(result.failures),
        "errors": len(result.errors),
    }


def run() -> dict[str, Any]:
    scenarios = _run_public_scenarios()
    upgrades = [
        _verify_start(version, fixtures)
        for version, fixtures in SUPPORTED_STARTS.items()
    ]
    evidence = {
        "supportedStartingVersions": sorted(SUPPORTED_STARTS),
        "currentVersion": 3,
        "upgrades": upgrades,
        "existingPublicScenarioCoverage": scenarios,
        "downgrade": {
            "supported": False,
            "statement": "Graph-store downgrade is unsupported in V1.",
        },
        "passed": scenarios["successful"] and all(item["passed"] for item in upgrades),
    }
    fixture_digests = {
        name: file_digest(FIXTURE_ROOT / name)
        for names in SUPPORTED_STARTS.values()
        for name in names
    }
    return receipt(
        "hocus_graph_store_upgrade_receipt",
        evidence,
        fixture_digests=fixture_digests,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    value = run()
    write_receipt(arguments.output, value)
    print(json.dumps(value["evidence"], indent=2, sort_keys=True))
    return 0 if value["evidence"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
