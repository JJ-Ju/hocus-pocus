"""SQLite connection boundary for the durable graph store."""

from __future__ import annotations

import sqlite3
from typing import Any

from .graph_store_plans import GraphStorePlanError


class GraphStoreSchemaError(RuntimeError):
    """Raised when a graph-store database cannot be migrated safely."""


def _storage_failure(error: sqlite3.Error) -> GraphStorePlanError:
    return GraphStorePlanError(f"Graph-store storage operation failed: {error}")


class _ClosingConnection(sqlite3.Connection):
    """Connection context that rolls back, closes, and translates SQLite errors."""

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        transaction_failure: sqlite3.Error | None = None
        close_failure: sqlite3.Error | None = None
        suppress = False
        try:
            suppress = bool(super().__exit__(exc_type, exc_value, traceback))
        except sqlite3.Error as error:
            transaction_failure = error
        try:
            self.close()
        except sqlite3.Error as error:
            close_failure = error
        if isinstance(exc_value, GraphStoreSchemaError):
            return False
        failure = transaction_failure or close_failure
        if failure is None and isinstance(exc_value, sqlite3.Error):
            failure = exc_value
        if failure is not None:
            raise _storage_failure(failure) from failure
        return suppress


def open_storage_connection(
    database: str,
    *,
    timeout: float = 5.0,
    pragmas: tuple[str, ...] = (),
) -> sqlite3.Connection:
    """Open one domain-adapted SQLite connection."""

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            database,
            timeout=timeout,
            factory=_ClosingConnection,
        )
        for statement in pragmas:
            connection.execute(statement)
        return connection
    except sqlite3.Error as error:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            try:
                connection.close()
            except sqlite3.Error:
                pass
        raise _storage_failure(error) from error
